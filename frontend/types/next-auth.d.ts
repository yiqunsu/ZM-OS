import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    backendToken: string;
    user: {
      id: string;
      role: string;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    uid: string;
    role: string;
    backendToken: string;
  }
}
