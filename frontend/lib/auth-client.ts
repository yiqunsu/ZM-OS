"use client";

import { signOut } from "next-auth/react";

const CASDOOR_PUBLIC_URL = process.env.NEXT_PUBLIC_CASDOOR_URL?.replace(/\/$/, "");
const CASDOOR_CLIENT_ID = process.env.NEXT_PUBLIC_CASDOOR_CLIENT_ID;

/**
 * Clear the local Auth.js session, then let the browser clear Casdoor's SSO
 * cookie. A browser-side form is required because a server-to-server logout
 * cannot remove the cookie owned by auth.zmorder.cn.
 */
export async function federatedSignOut(): Promise<void> {
  await signOut({ redirect: false });

  if (!CASDOOR_PUBLIC_URL) {
    window.location.assign("/login");
    return;
  }

  const form = document.createElement("form");
  form.method = "POST";
  form.action = `${CASDOOR_PUBLIC_URL}/api/logout`;

  const redirect = document.createElement("input");
  redirect.type = "hidden";
  redirect.name = "post_logout_redirect_uri";
  redirect.value = `${window.location.origin}/login`;
  form.appendChild(redirect);

  if (CASDOOR_CLIENT_ID) {
    const clientId = document.createElement("input");
    clientId.type = "hidden";
    clientId.name = "client_id";
    clientId.value = CASDOOR_CLIENT_ID;
    form.appendChild(clientId);
  }

  document.body.appendChild(form);
  form.submit();
}
