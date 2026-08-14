import type { DefaultSession } from "next-auth";

type FilmOSRole = "OWNER" | "OPERATOR";

declare module "next-auth" {
  interface Session {
    backendToken?: string;
    error?: "RefreshTokenError";
    user: {
      id?: string;
      role?: FilmOSRole;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    uid?: string;
    role?: FilmOSRole;
    backendToken?: string;
    accessTokenExpires?: number;
    refreshToken?: string;
    idToken?: string;
    authError?: "RefreshTokenError";
  }
}
