// 시연이네 그림맞추기 PWA 서비스 워커 (오프라인 완전 지원 및 캐시 무효화)
const CACHE_NAME = 'siyeon-mahjong-v1.5.19';

// 최초 구동 시 오프라인 실행을 위해 필수 사전 다운로드(Pre-cache)할 리소스 목록
const PRECACHE_URLS = [
  './',
  './MahjongMain.html',
  './manifest.json',
  './assets/icon-192.png',
  './assets/icon-512.png',
  './assets/mahjong_splash.jpg',
  './assets/quick_rules_guide.jpg',
  './assets/tiles/g_bing.webp',
  './assets/tiles/g_ding.webp',
  './assets/tiles/g_geng.webp',
  './assets/tiles/g_gui.webp',
  './assets/tiles/g_ji.webp',
  './assets/tiles/g_jia.webp',
  './assets/tiles/g_ren.webp',
  './assets/tiles/g_wu.webp',
  './assets/tiles/g_xin.webp',
  './assets/tiles/g_yi.webp',
  './assets/tiles/oryong_black.webp',
  './assets/tiles/oryong_blue.webp',
  './assets/tiles/oryong_coin.webp',
  './assets/tiles/oryong_envelope.webp',
  './assets/tiles/oryong_green.webp',
  './assets/tiles/oryong_koi.webp',
  './assets/tiles/oryong_lion.webp',
  './assets/tiles/oryong_phoenix.webp',
  './assets/tiles/oryong_purple.webp',
  './assets/tiles/oryong_red.webp',
  './assets/tiles/oryong_tiger.webp',
  './assets/tiles/oryong_turtle.webp',
  './assets/tiles/oryong_white.webp',
  './assets/tiles/oryong_yellow.webp',
  './assets/tiles/s_bijian.webp',
  './assets/tiles/s_geobjae.webp',
  './assets/tiles/s_jeonggwan.webp',
  './assets/tiles/s_jeongin.webp',
  './assets/tiles/s_jeongjae.webp',
  './assets/tiles/s_pyeongwan.webp',
  './assets/tiles/s_pyeonin.webp',
  './assets/tiles/s_pyeonjae.webp',
  './assets/tiles/s_sangpwan.webp',
  './assets/tiles/s_siksin.webp',
  './assets/tiles/wx_earth.webp',
  './assets/tiles/wx_fire.webp',
  './assets/tiles/wx_metal.webp',
  './assets/tiles/wx_water.webp',
  './assets/tiles/wx_wood.webp',
  './assets/tiles/yy_yang.webp',
  './assets/tiles/yy_yin.webp',
  './assets/tiles/z_chen.webp',
  './assets/tiles/z_chou.webp',
  './assets/tiles/z_hai.webp',
  './assets/tiles/z_mao.webp',
  './assets/tiles/z_shen.webp',
  './assets/tiles/z_si.webp',
  './assets/tiles/z_wei.webp',
  './assets/tiles/z_wu.webp',
  './assets/tiles/z_xu.webp',
  './assets/tiles/z_yin.webp',
  './assets/tiles/z_you.webp',
  './assets/tiles/z_zi.webp',
  './assets/dragons/dragon_gold_black_tile.png',
  './assets/dragons/dragon_gold_blue_tile.png',
  './assets/dragons/dragon_gold_green_tile.png',
  './assets/dragons/dragon_gold_master.png',
  './assets/dragons/dragon_gold_purple_tile.png',
  './assets/dragons/dragon_gold_red_tile.png',
  './assets/dragons/dragon_gold_white_tile.png',
  './assets/dragons/dragon_gold_yellow_tile.png',
  './assets/dragons/dragon_head_black_tile.webp',
  './assets/dragons/dragon_head_blue_tile.webp',
  './assets/dragons/dragon_head_green_tile.webp',
  './assets/dragons/dragon_head_purple_tile.webp',
  './assets/dragons/dragon_head_red_tile.webp',
  './assets/dragons/dragon_head_white_tile.webp',
  './assets/dragons/dragon_head_yellow_tile.webp',
  './assets/dragons/gold_dragon_head_pure.png',
  './assets/dragons/gold_dragon_head_tile.webp',
  './assets/emblems/crown.jpg',
  './assets/emblems/jade.jpg',
  './assets/emblems/ruby.jpg',
  './assets/emblems/sapphire.jpg'
];

// 1. 서비스 워커 설치: 필수 리소스 전량 사전 다운로드
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // 개별 리소스 실패가 전체 캐시 실패로 이어지지 않도록 안전 병렬 처리
      return Promise.all(
        PRECACHE_URLS.map((url) => {
          return cache.add(url).catch((err) => {
            console.warn('[SW Precache] Skip failed asset:', url, err);
          });
        })
      );
    }).then(() => self.skipWaiting())
  );
});

// 2. 서비스 워커 활성화: 이전 구버전 캐시 자동 전량 폐기
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// 3. 페치(Fetch) 요청 제어:
//    - HTML(문서): Network-First (온라인 시 최신 코드 우선 수신 ➔ 실패/오프라인 시 캐시)
//    - 이미지/정적 에셋: Cache-First (캐시 우선 0ms 로딩 ➔ 없으면 네트워크에서 받아 캐시에 보관)
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // POST나 타 오리진 특수 요청 제외
  if (req.method !== 'GET') return;

  // A. HTML 문서 요청: Network-First 전략
  const isHtml = req.mode === 'navigate' ||
                 req.destination === 'document' ||
                 url.pathname.endsWith('.html') ||
                 url.pathname.endsWith('/');

  if (isHtml) {
    event.respondWith(
      fetch(req).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, responseClone));
        }
        return networkResponse;
      }).catch(() => {
        // 네트워크 단절(오프라인) 시 로컬 캐시에서 즉시 응답
        return caches.match(req).then((cached) => {
          return cached || caches.match('./MahjongMain.html');
        });
      })
    );
    return;
  }

  // B. 이미지 및 기타 정적 에셋: Cache-First 전략
  event.respondWith(
    caches.match(req).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(req).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          if (url.origin === location.origin) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, responseClone));
          }
        }
        return networkResponse;
      }).catch(() => {
        // 캐시에도 없고 오프라인인 경우
        return new Response('Offline resource unavailable', { status: 503, statusText: 'Service Unavailable' });
      });
    })
  );
});

// 4. 메시지 이벤트: 즉시 활성화 트리거 지원
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
