// The Scoreboard moved to /scoreboard.html and the Weekly Report to /report.html. The old addresses, /sunday.html and
// /recap.html, are still written by the home computer's build with last week's data, so anyone who lands on them is
// sent to the live pages. Nothing else is touched or cached.
// To switch this off: replace the fetch handler below with nothing and keep the file, so browsers pick up the change.
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', function (e) {
  var u = new URL(e.request.url);
  if (e.request.mode !== 'navigate' || u.origin !== self.location.origin) return;
  if (u.searchParams.has('computer')) return;      // /sunday.html?computer shows the home computer's own page
  if (u.pathname === '/sunday.html') e.respondWith(Response.redirect('/scoreboard.html', 302));
  else if (u.pathname === '/recap.html') e.respondWith(Response.redirect('/report.html', 302));
});
