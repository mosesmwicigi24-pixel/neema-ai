import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const API = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";

/** Decode JWT exp claim without verifying signature (safe client-side). */
function jwtExpiry(token: string): number {
    try {
        return JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString()).exp ?? 0;
    } catch { return 0; }
}

/** Call /api/auth/refresh — returns new token pair or null on failure. */
async function doRefresh(refreshToken: string): Promise<{ access_token: string; refresh_token: string } | null> {
    try {
        const res = await fetch(`${API}/api/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return null;
        return res.json();
    } catch { return null; }
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
                if (!credentials?.email || !credentials?.password)
                    throw new Error("Missing email or password");

                const res = await fetch(`${API}/api/auth/login`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email: credentials.email, password: credentials.password }),
                });
                if (!res.ok) throw new Error("Invalid credentials");
                const data = await res.json();

                // Return everything we need; NextAuth passes this object to jwt()
                return {
                    id:           data.agent_id ?? data.id,
                    email:        data.email,
                    name:         data.name ?? data.email,
                    accessToken:  data.access_token,
                    refreshToken: data.refresh_token,
                    role:         data.role ?? "agent",
                    isSuperuser: data.is_superuser,
                };
            },
        }),
    ],

    callbacks: {
        async jwt({ token, user }) {
            // ── First sign-in: seed the token from authorize() return value ──
            if (user) {
                token.accessToken       = (user as any).accessToken  as string;
                token.refreshToken      = (user as any).refreshToken as string;
                token.accessTokenExpiry = jwtExpiry((user as any).accessToken);
                token.id                = user.id;
                token.role              = (user as any).role ?? "agent";
                token.isSuperuser       = (user as any).isSuperuser;
                return token;
            }

            // ── Subsequent calls: check expiry and refresh proactively ───────
            const nowSec = Math.floor(Date.now() / 1000);
            const expiry = (token.accessTokenExpiry as number) ?? 0;

            // Still valid with >60s buffer — return as-is
            if (expiry - nowSec > 60) return token;

            // Token is expired (or within 60s of expiry) — try silent refresh
            const refreshToken = token.refreshToken as string | undefined;
            if (!refreshToken) return { ...token, error: "RefreshTokenMissing" };

            const refreshed = await doRefresh(refreshToken);
            if (!refreshed) return { ...token, error: "RefreshTokenExpired" };

            return {
                ...token,
                accessToken:       refreshed.access_token,
                refreshToken:      refreshed.refresh_token,
                accessTokenExpiry: jwtExpiry(refreshed.access_token),
                error:             undefined,
            };
        },

        async session({ session, token }) {
            (session as any).accessToken  = token.accessToken;
            (session as any).refreshToken = token.refreshToken;
            (session as any).role         = token.role;
            (session as any).error        = token.error;      // propagated to client
            session.user.id               = token.id as string;
            session.user.role             = token.role as string;           
            session.user.isSuperuser      = token.isSuperuser as boolean;
            return session;
        },
    },

    pages:   { signIn: "/login" },
    // 30-day cookie — NextAuth will still call jwt() to check/refresh the token
    session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 },
});