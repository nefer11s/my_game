// 시연이네 그림맞추기 PWA 서비스 워커
const CACHE_NAME = 'siyeon-mahjong-v1.5.9';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // PWA 필수 조건: fetch 핸들러 등록
  // 네트워크 요청을 그대로 통과시키되 실패 시 캐시 응답
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});
