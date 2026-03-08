import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const handler = NextAuth({
    providers: [
        CredentialsProvider({
            name: "credentials",
            credentials: {
                email: { label: "Email", type: "email" },
                password: { label: "Password", type: "password" },
            },
            async authorize(credentials) {
                try {
                    const res = await fetch(
                        `${process.env.API_INTERNAL_URL ?? "http://api:8000"}/api/auth/login`,
                        {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                email: credentials?.email,
                                password: credentials?.password,
                            }),
                        },
                    );
                    if (!res.ok) return null;
                    const data = await res.json();
                    return {
                        id: data.agent_id ?? "unknown",
                        email: credentials?.email as string,
                        accessToken: data.access_token,
                    };
                } catch {
                    return null;
                }
            },
        }),
    ],
    callbacks: {
        async jwt({ token, user }) {
            if (user) {
                token.accessToken = (user as any).accessToken;
                token.id = user.id;
            }
            return token;
        },
        async session({ session, token }) {
            (session as any).accessToken = token.accessToken;
            session.user.id = token.id as string;
            return session;
        },
    },
    pages: { signIn: "/login" },
    session: { strategy: "jwt" },
    secret: process.env.NEXTAUTH_SECRET,
});

export { handler as GET, handler as POST };
