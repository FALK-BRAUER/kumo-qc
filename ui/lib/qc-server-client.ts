// Server-only module — never import this in client components.
// QC API auth: Authorization: Basic base64(userId:SHA256(apiToken:timestamp))
// plus Timestamp header (unix seconds).

import crypto from 'crypto';

const BASE_URL = 'https://www.quantconnect.com/api/v2';

function buildHeaders(): HeadersInit {
  const userId = process.env.QC_USER_ID!;
  const apiToken = process.env.QC_API_TOKEN!;
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const hash = crypto.createHash('sha256').update(`${apiToken}:${timestamp}`).digest('hex');
  const credentials = Buffer.from(`${userId}:${hash}`).toString('base64');
  return {
    'Authorization': `Basic ${credentials}`,
    'Timestamp': timestamp,
  };
}

export async function qcFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: buildHeaders(),
    cache: 'no-store',
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`QC API ${res.status} at ${path}: ${body}`);
  }
  const data = await res.json();
  if (data.success === false) {
    throw new Error(`QC API error: ${data.errors?.join(', ') || 'unknown'}`);
  }
  return data as T;
}
