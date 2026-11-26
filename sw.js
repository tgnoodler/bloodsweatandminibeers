// The Scoreboard moved to /scoreboard.html. The old address, /sunday.html, is still written by the home computer's
// build with last week's data, so anyone who lands there is sent to the live page. Nothing else is touched or cached.
// To switch this off: replace the fetch handler below with nothing and keep the file, so browsers pick up the change.
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', function (e) {
  var u = new URL(e.request.url);
  if (e.request.mode === 'navigate' && u.origin === self.location.origin && u.pathname === '/sunday.html') {
    e.respondWith(Response.redirect('/scoreboard.html', 302));
  }
});
