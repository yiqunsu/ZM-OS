import NextAuth from "next-auth";
import type { JWT } from "next-auth/jwt";
import Credentials from "next-auth/providers/credentials";
import { SignJWT } from "jose";

const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000";
const AUTH_PROVIDER = process.env.AUTH_PROVIDER ?? "local";
const CASDOOR_ISSUER = (process.env.CASDOOR_ISSUER ?? "http://casdoor.invalid").replace(/\/$/, "");
const CASDOOR_PUBLIC_URL = (
  process.env.CASDOOR_PUBLIC_URL ?? CASDOOR_ISSUER
).replace(/\/$/, "");
const CASDOOR_INTERNAL_URL = (
  process.env.CASDOOR_INTERNAL_URL ?? CASDOOR_PUBLIC_URL
).replace(/\/$/, "");
const CASDOOR_CLIENT_ID = process.env.CASDOOR_CLIENT_ID ?? "not-configured";
const CASDOOR_CLIENT_SECRET = process.env.CASDOOR_CLIENT_SECRET ?? "not-configured";
const ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 30;
const localSecretKey = new TextEncoder().encode(process.env.AUTH_SECRET);

type FilmOSRole = "OWNER" | "OPERATOR";

interface BackendUser {
  id: string;
  email: string;
  role: FilmOSRole;
}

interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  id_token?: string;
}

function isFilmOSRole(value: unknown): value is FilmOSRole {
  return value === "OWNER" || value === "OPERATOR";
}

async function loadBackendUser(accessToken: string): Promise<BackendUser> {
  const response = await fetch(`${BACKEND_INTERNAL_URL}/api/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("FastAPI 拒绝了 Casdoor access token");
  }

  const value = (await response.json()) as Partial<BackendUser>;
  if (!value.id || !value.email || !isFilmOSRole(value.role)) {
    throw new Error("FastAPI 返回了无效的用户信息");
  }

  return { id: value.id, email: value.email, role: value.role };
}

async function refreshAccessToken(token: JWT): Promise<JWT> {
  if (!token.refreshToken) {
    return { ...token, backendToken: undefined, authError: "RefreshTokenError" };
  }

  try {
    const response = await fetch(`${CASDOOR_INTERNAL_URL}/api/login/oauth/access_token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: CASDOOR_CLIENT_ID,
        client_secret: CASDOOR_CLIENT_SECRET,
        grant_type: "refresh_token",
        refresh_token: token.refreshToken,
      }),
      cache: "no-store",
    });

    const refreshed = (await response.json()) as TokenResponse;
    if (!response.ok || !refreshed.access_token || !refreshed.expires_in) {
      throw new Error("Casdoor refresh token 请求失败");
    }

    const user = await loadBackendUser(refreshed.access_token);
    return {
      ...token,
      uid: user.id,
      email: user.email,
      role: user.role,
      backendToken: refreshed.access_token,
      accessTokenExpires: Date.now() + refreshed.expires_in * 1000,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      idToken: refreshed.id_token ?? token.idToken,
      authError: undefined,
    };
  } catch {
    console.error("Casdoor access token refresh failed");
    return { ...token, backendToken: undefined, authError: "RefreshTokenError" };
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: AUTH_PROVIDER === "local"
    ? [
        Credentials({
          credentials: { email: {}, password: {} },
          authorize: async (credentials) => {
            const response = await fetch(`${BACKEND_INTERNAL_URL}/api/auth/login`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                email: credentials.email,
                password: credentials.password,
              }),
            });
            if (!response.ok) return null;
            const user = (await response.json()) as BackendUser;
            return { id: user.id, email: user.email, role: user.role };
          },
        }),
      ]
    : [{
      id: "casdoor",
      name: "Casdoor",
      type: "oidc",
      issuer: CASDOOR_ISSUER,
      clientId: CASDOOR_CLIENT_ID,
      clientSecret: CASDOOR_CLIENT_SECRET,
      authorization: {
        url: `${CASDOOR_PUBLIC_URL}/login/oauth/authorize`,
        params: { scope: "openid profile email offline_access" },
      },
      token: `${CASDOOR_INTERNAL_URL}/api/login/oauth/access_token`,
      userinfo: `${CASDOOR_INTERNAL_URL}/api/userinfo`,
      jwks_endpoint: `${CASDOOR_INTERNAL_URL}/.well-known/jwks`,
      checks: ["pkce", "state", "nonce"],
      profile(profile) {
        if (!profile.sub || !profile.email) {
          throw new Error("Casdoor 用户资料缺少 sub 或 email");
        }
        return {
          id: profile.sub,
          email: profile.email,
          name: profile.name ?? profile.displayName ?? profile.email,
          image: profile.picture ?? null,
        };
      },
    }],
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  pages: { signIn: "/login" },
  trustHost: true,
  callbacks: {
    async jwt({ token, account, user }) {
      if (account) {
        if (account.provider === "credentials" && user) {
          const role = (user as BackendUser).role;
          const backendToken = await new SignJWT({
            sub: user.id,
            email: user.email,
            role,
          })
            .setProtectedHeader({ alg: "HS256" })
            .setIssuedAt()
            .setExpirationTime("8h")
            .sign(localSecretKey);
          return {
            ...token,
            uid: user.id,
            email: user.email,
            role,
            backendToken,
            accessTokenExpires: Date.now() + 8 * 60 * 60 * 1000,
          };
        }

        if (!account.access_token || !account.expires_at || !account.refresh_token) {
          throw new Error("Casdoor 未返回完整的 access/refresh token");
        }

        const backendUser = await loadBackendUser(account.access_token);
        return {
          ...token,
          uid: backendUser.id,
          email: backendUser.email,
          role: backendUser.role,
          backendToken: account.access_token,
          accessTokenExpires: account.expires_at * 1000,
          refreshToken: account.refresh_token,
          idToken: account.id_token,
          authError: undefined,
        };
      }

      if (AUTH_PROVIDER === "local") return token;

      const refreshAt = (token.accessTokenExpires ?? 0) - ACCESS_TOKEN_REFRESH_SKEW_SECONDS * 1000;
      if (token.backendToken && Date.now() < refreshAt) {
        return token;
      }

      return refreshAccessToken(token);
    },
    async session({ session, token }) {
      session.backendToken = token.backendToken;
      session.error = token.authError;
      if (token.uid) session.user.id = token.uid;
      if (token.role) session.user.role = token.role;
      return session;
    },
  },
});
