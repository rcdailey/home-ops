// Converges Silo's single sign-on on Pocket ID through Silo's admin API: the public URL, the
// OpenID Connect plugin, its settings, and the sign-in binding. Each step writes only when the
// stored value differs, so scheduled runs also undo changes made in the web app.
//
// Limits: the admin API never returns stored secrets, so a rotated client secret is applied only
// after the plugin's stored secret is cleared or the plugin is reinstalled.

const PLUGIN_ID = "silo.auth.oidc";
const CAPABILITY_ID = "oidc";

const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set`);
  return value;
};

const baseUrl = required("SILO_URL");
const apiKey = required("SILO_API_KEY");
const publicUrl = required("SILO_PUBLIC_URL");
const connection = {
  issuer_url: required("OIDC_ISSUER_URL"),
  client_id: required("OIDC_CLIENT_ID"),
};
const clientSecret = required("OIDC_CLIENT_SECRET");
const buttonLabel = { value: required("OIDC_BUTTON_LABEL") };
const binding = {
  capability_id: CAPABILITY_ID,
  enabled: true,
  display_order: 0,
  default_login: false,
  // Creates a Silo account on first sign-in; the Pocket ID client limits who can sign in.
  auto_provision: true,
};

async function request(method, path, body, headers = {}) {
  const response = await fetch(new URL(path, baseUrl), {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(body && { "Content-Type": "application/json" }),
      ...headers,
    },
    body: body && JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
  }
  return response.status === 204 ? undefined : response.json();
}

async function listAll(path) {
  const items = [];
  let cursor;
  do {
    const query = new URLSearchParams({ limit: "200", ...(cursor && { cursor }) });
    const page = await request("GET", `${path}?${query}`);
    items.push(...page.items);
    cursor = page.page?.has_more ? page.page.next_cursor : undefined;
  } while (cursor);
  return items;
}

const compareVersions = (a, b) => {
  const [x, y] = [a, b].map((v) => v.split(/[.-]/).map((part) => Number.parseInt(part, 10) || 0));
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const diff = (x[i] ?? 0) - (y[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
};

const matches = (stored, desired) =>
  Object.entries(desired).every(([key, value]) => stored?.[key] === value);

async function reconcilePublicUrl() {
  const key = "server.public_url";
  const { value } = await request("GET", `/api/v2/admin/settings/${key}`);
  if (value === publicUrl) return;
  await request("PUT", `/api/v2/admin/settings/${key}`, { value: publicUrl }, { "If-Match": "*" });
  console.log(`set ${key}`);
}

async function ensureInstalled() {
  const installations = await listAll("/api/v2/admin/plugins/installations");
  const installed = installations.find((i) => i.plugin_id === PLUGIN_ID);
  if (installed) return installed;

  const [latest] = (await listAll("/api/v2/admin/plugins/catalog"))
    .filter((entry) => entry.plugin_id === PLUGIN_ID)
    .sort((a, b) => compareVersions(b.version, a.version));
  if (!latest) throw new Error(`${PLUGIN_ID} is not in the plugin catalog`);

  const { repository_id, plugin_id, version } = latest;
  console.log(`installing ${plugin_id} ${version}`);
  return request("POST", "/api/v2/admin/plugins/installations", {
    repository_id,
    plugin_id,
    version,
  });
}

async function reconcilePlugin(installation) {
  const path = `/api/v2/admin/plugins/installations/${installation.id}`;

  if (!installation.enabled || installation.update_policy !== "auto") {
    await request("PUT", path, { enabled: true, update_policy: "auto" });
    console.log("enabled plugin with automatic updates");
  }

  const stored = Object.fromEntries((installation.global_configs ?? []).map((c) => [c.key, c]));

  const storedConnection = stored.connection;
  const hasSecret = storedConnection?.configured_secrets?.includes("client_secret");
  if (!matches(storedConnection?.value, connection) || !hasSecret) {
    const value = { ...connection, ...(!hasSecret && { client_secret: clientSecret }) };
    await request("PUT", `${path}/config`, { key: "connection", value });
    console.log("set provider connection");
  }

  if (!matches(stored.display_name?.value, buttonLabel)) {
    await request("PUT", `${path}/config`, { key: "display_name", value: buttonLabel });
    console.log("set button label");
  }

  const storedBinding = installation.auth_bindings?.find((b) => b.capability_id === CAPABILITY_ID);
  if (!matches(storedBinding, binding)) {
    await request("PUT", `${path}/auth-binding`, binding);
    console.log("enabled sign-in binding");
  }
}

await reconcilePublicUrl();
await reconcilePlugin(await ensureInstalled());
console.log("sign-in configuration converged");
