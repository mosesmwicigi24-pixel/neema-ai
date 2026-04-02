import NextAuth from "next-auth";

declare module "next-auth" {
    interface Session {
        accessToken?: string;
        user: {
            id: string;
            role: string;           
            isSuperuser: boolean;
        } & DefaultSession["user"];
    }
}

declare module "next-auth/jwt" {
    interface JWT {
        accessToken?: string;
        id?: string;            
        role?: string;          
        isSuperuser?: boolean;  
    }
}
