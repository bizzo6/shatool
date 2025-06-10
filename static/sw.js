const CACHE_NAME = 'shatool-cache-v1';
const urlsToCache = [
    '/',
    '/static/logo_icon.png',
    '/static/logo_sidebar.png',
    '/static/icon-192x192.png',
    '/static/icon-512x512.png',
    '/static/icon-144x144.png',
    '/static/manifest.json'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    return response;
                }

                // Clone the request because it can only be used once
                const fetchRequest = event.request.clone();

                // Add credentials for authenticated requests
                const fetchOptions = {
                    credentials: 'include',
                    headers: new Headers({
                        'Accept': 'application/json'
                    })
                };

                return fetch(fetchRequest, fetchOptions)
                    .then(response => {
                        // Check if we received a valid response
                        if (!response || response.status !== 200 || response.type !== 'basic') {
                            return response;
                        }

                        // Clone the response because it can only be used once
                        const responseToCache = response.clone();

                        // Only cache requests with supported schemes (http/https)
                        if (event.request.url.startsWith('http')) {
                            caches.open(CACHE_NAME)
                                .then(cache => {
                                    cache.put(event.request, responseToCache);
                                });
                        }

                        return response;
                    })
                    .catch(error => {
                        console.error('Fetch failed:', error);
                        // Return a fallback response if fetch fails
                        if (event.request.url.includes('tailwindcss.com')) {
                            return new Response('/* Tailwind CSS fallback */', {
                                headers: { 'Content-Type': 'text/css' }
                            });
                        }
                        throw error;
                    });
            })
    );
});

// Clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
}); 