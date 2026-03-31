import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const API = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";

// Decode JWT payload without verifying signature (client-side safe)
function parseJwtExpiry(token: string): number {
    try {
        const payload = JSON.parse(
            Buffer.from(token.split(".")[1], "base64url").toString()
        );
        return (payload.exp as number) ?? 0;
    } catch {
        return 0;
    }
}

// Call the backend refresh endpoint and return new tokens, or null on failure
async function refreshTokens(refreshToken: string): Promise<{
    access_token: string;
    refresh_token: string;
} | null> {
    try {
        const res = await fetch(`${API}/api/auth/refresh`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        return {
            access_token:  data.access_token,
            refresh_token: data.refresh_token,
        };
    } catch {
        return null;
    }
}

import type { Session } from "next-auth";

// Extend the Session type to include custom properties
declare module "next-auth" {
    interface Session {
        accessToken?: string;
        refreshToken?: string;
        user: {
            id?: string;
            name?: string | null;
            email?: string | null;
        };
        role?: string;
        error?: string;
    }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
    providers: [
        CredentialsProvider({
            name: "credentials",
            credentials: {
                email:    { label: "Email",    type: "email"    },
                password: { label: "Password", type: "password" },
            },
            async authorize(credentials) {
                if (!credentials?.email || !credentials?.password) {
                    throw new Error("Missing email or password");
                }
                const res = await fetch(`${API}/api/auth/login`, {
                    method:  "POST",
                    headers: { "Content-Type": "application/json" },
                    body:    JSON.stringify({
                        email:    credentials.email,
                        password: credentials.password,
                    }),
                });
                if (!res.ok) throw new Error("Invalid credentials");
                const data = await res.json();
                return {
                    id:           data.agent_id,
                    email:        data.email,
                    name:         data.name ?? data.email,
                    accessToken:  data.access_token,
                    refreshToken: data.refresh_token,
                    role:         data.role ?? "agent",
                };
            },
        }),
    ],

    callbacks: {
        async jwt({ token, user }) {
            // First sign-in — store everything from the authorize() return value
            if (user) {
                token.accessToken  = (user as any).accessToken  as string;
                token.refreshToken = (user as any).refreshToken as string;
                token.accessTokenExpiry = parseJwtExpiry((user as any).accessToken);
                token.id   = user.id;
                token.role = (user as any).role ?? "agent";
                return token;
            }

            // On every subsequent getSession()/useSession() call:
            // If access token still has >60 seconds left, return as-is
            const now = Math.floor(Date.now() / 1000);
            const exp = (token.accessTokenExpiry as number) ?? 0;
            if (exp - now > 60) return token;

            // Access token is expired (or about to) — try to refresh silently
            const refreshToken = token.refreshToken as string | undefined;
            if (!refreshToken) {
                // No refresh token — force re-login
                return { ...token, error: "RefreshTokenMissing" };
            }

            const refreshed = await refreshTokens(refreshToken);
            if (!refreshed) {
                // Refresh failed (token revoked / server error) — force re-login
                return { ...token, error: "RefreshTokenExpired" };
            }

            return {
                ...token,
                accessToken:        refreshed.access_token,
                refreshToken:       refreshed.refresh_token,
                accessTokenExpiry:  parseJwtExpiry(refreshed.access_token),
                error:              undefined,
            };
        },

        async session({ session, token }) {
            session.accessToken  = token.accessToken  as string;
            session.refreshToken = token.refreshToken as string;
            session.user.id      = token.id           as string;
            (session as any).role  = token.role;
            (session as any).error = token.error;   // propagate error to client
            return session;
        },
    },

    pages:   { signIn: "/login" },
    session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 }, // 30 days cookie
});