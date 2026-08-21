import http from 'k6/http';
import { check, sleep } from 'k6';

// stress profile — ramps up fast to find breaking point
export const options = {
  stages: [
    { duration: '30s', target: 20 },
    { duration: '1m', target: 100 },
    { duration: '30s', target: 200 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1200'],
  },
};

const BASE = __ENV.TARGET_URL || 'https://example.com';

export default function () {
  const res = http.get(BASE);
  check(res, {
    'status 200': (r) => r.status === 200,
    'p95 < 800': (r) => r.timings.duration < 800,
  });
  sleep(1);
}
