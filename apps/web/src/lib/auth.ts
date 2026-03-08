import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import axios from "axios";

export const { handlers, auth, signIn, signOut } = NextAuth({
    providers: [
        CredentialsProvider({
            name: "credentials",
            credentials: {
                email: { label: "Email", type: "email" },
                password: { label: "Password", type: "password" },
            },
            async authorize(credentials) {
                if (!credentials?.email || !credentials?.password) {
                    throw new Error("Missing email or password");
                }

                const { data } = await axios.post(
                    `${process.env.API_INTERNAL_URL}/api/auth/login`,
                    {
                        email: credentials.email,
                        password: credentials.password,
                    },
                );

                return {
                    id: data.agent_id,
                    email: data.email,
                    accessToken: data.access_token,
                };
            },
        }),
    ],
    callbacks: {
        async jwt({ token, user }) {
            if (user) {
                token.accessToken = (user as any).accessToken;
                token.refreshToken = (user as any).refreshToken;
                token.id = user.id;
            }
            return token;
        },
        async session({ session, token }) {
            session.accessToken = token.accessToken as string;
            session.user.id = token.id as string;
            return session;
        },
    },
    pages: { signIn: "/login" },
    session: { strategy: "jwt" },
});
