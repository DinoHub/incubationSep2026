# Pointing the server at a real provider

The bundled Keycloak exists so the stack runs from a clean checkout. Nothing
about `auth.py` is Keycloak-specific: it discovers the signing keys from the
issuer's own metadata and reads roles from a configurable claim, so moving to a
real provider is configuration rather than code.

## The four knobs

| Variable | What it is | Getting it wrong looks like |
| --- | --- | --- |
| `OIDC_ISSUER` | The issuer, character-for-character as it appears in the `iss` claim | Every token rejected, 401 on everything |
| `OIDC_AUDIENCE` | The identifier this server is registered under | Nothing — which is the problem, see below |
| `OIDC_ROLES_CLAIM` | Dotted path to the claim holding roles | Authentication works, every role check denies |
| `OIDC_JWKS_URL` | Only for a provider without discovery | Startup fails fetching discovery |

Copy the issuer from the provider's console rather than typing it. A trailing
slash is part of the string for some providers and absent for others, and PyJWT
compares it exactly.

## Set the audience

Leave `OIDC_AUDIENCE` unset and the server accepts **any** token the issuer
signed. On a shared tenant that includes tokens minted for entirely different
services — a caller with a legitimate token for some unrelated app can call your
tools. The check is one string comparison, and skipping it is the single most
common way an otherwise correct setup ends up not being a boundary at all.

The generated default omits it because the bundled Keycloak realm defines no
audience mapper, which keeps the first run working. Set it as soon as the issuer
is real.

## Where each provider puts roles

Authentication and authorization fail differently here, and it is worth knowing
which you are looking at: if tokens verify but every role check denies, the
roles claim is wrong, not the issuer.

| Provider | `OIDC_ROLES_CLAIM` | Notes |
| --- | --- | --- |
| Keycloak | `realm_access.roles` | The default. Client roles live at `resource_access.<client-id>.roles` instead. |
| Auth0 | `permissions` | Requires RBAC plus "Add Permissions in the Access Token" on the API. `scope` is a space-delimited string, which `auth.py` also handles. |
| Okta | `scp` | An array. Group-based instead: add a groups claim and point at it. |
| Entra ID | `roles` | App roles assigned to the service principal. `scp` carries delegated scopes, which is a different thing. |
| Anything standard | `scope` | Space-delimited. `auth.py` falls back to `scope`, then `scp`, when the configured path is absent. |

Dotted paths walk nested objects, so `resource_access.my-api.roles` works. Both
shapes are handled: a JSON array, and the space-delimited string the standard
`scope` claim uses.

## Machine identities, not users

Every caller here is a program, so the grant is Client Credentials: the client
authenticates as itself with an ID and a secret, and no human logs in. In the
generated realm that is `serviceAccountsEnabled: true` with
`standardFlowEnabled: false` and `directAccessGrantsEnabled: false` — no login
page and no password grant, only the one flow that fits.

Equivalents: Auth0 calls it a Machine-to-Machine application, Okta a service app
with client credentials, Entra ID a client credentials flow against an app
registration.

**One identity per privilege level, not one client that asks for a role.** If a
single credential could request either privilege, holding it *is* holding both,
and the secret becomes the entire boundary — leaking it leaks everything.
Separate identities are what make a leaked read-only credential merely
embarrassing.

Keycloak detail worth knowing: roles attach to a hidden auto-created
`service-account-<clientId>` user, not to the client. That is why the generated
realm lists both roles on the writer's service-account user, and why the writer
is not "inheriting" from the reader — each grant is independent and happens to be
a superset.

## Token lifetime

The generated realm sets `accessTokenLifespan: 300`, so tokens expire in five
minutes. Short lifetimes are the main defence against a leaked token staying
useful; a caller that needs longer asks for another one, which costs a single
HTTP request. Resist raising it because a long-running job hit an expiry — fetch
a fresh token instead.

## What the bundled Keycloak is not

It runs `start-dev`: plain HTTP, an in-memory-ish dev database, a fixed
`admin`/`admin` password, and client secrets committed to the repository. It is a
development identity provider. Do not deploy it, and do not copy those secrets
into anything real.

Two more things the generated setup does not do, both worth adding before this
faces anything untrusted: TLS in front of the resource server, since a bearer
token on plain HTTP is readable by anything on the path, and any form of rate
limiting on the token endpoint.
