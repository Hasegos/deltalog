export async function onRequest({ request, env, next }) {
  if (request.headers.get("X-Snapshot-Key") === env.SNAPSHOT_KEY) return next();
  const { pathname } = new URL(request.url);
  const path = pathname.startsWith("/_f/") ? "/" : pathname;
  return Response.redirect("https://deltalog.kr" + path, 302);
}