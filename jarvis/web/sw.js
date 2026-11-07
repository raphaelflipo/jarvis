/* Service worker de Jarvis : affiche les notifications envoyées par le Mac (chiffrées de bout en bout) et ouvre la
   bonne tâche quand on touche la notification. Aucun cache : l'app reste toujours à jour. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Jarvis", {
    body: d.body || "",
    tag: d.tag || undefined,
    icon: "/static/icon.png",
    badge: "/static/icon.png",
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil((async () => {
    const list = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of list) {
      if ("focus" in c) {
        try { await c.navigate(url); } catch (_) {}
        return c.focus();
      }
    }
    return self.clients.openWindow(url);
  })());
});
