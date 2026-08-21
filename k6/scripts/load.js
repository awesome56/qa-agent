import http from 'k6/http';
import { check, sleep } from 'k6';

// load / soak — steady state
export const options = {
  vus: 50,
  duration: '5m',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800', 'p(99)<1200'],
  },
};

const BASE = __ENV.TARGET_URL || 'https://example.com';

export default function () {
  const res = http.get(BASE);
  check(res, { 'status 200': (r) => r.status === 200 });
  // also hit a second endpoint if SPA
  http.get(`${BASE}/api/health`);
  sleep(0.5);
}
