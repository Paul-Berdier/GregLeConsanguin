/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'i.ytimg.com' },
      { protocol: 'https', hostname: 'img.youtube.com' },
      { protocol: 'https', hostname: 'cdn.discordapp.com' },
      { protocol: 'https', hostname: 'i.scdn.co' },
      { protocol: 'https', hostname: 'mosaic.scdn.co' },
    ],
  },

  async rewrites() {
    // In Railway, api.railway.internal:3000 is the internal API service.
    // Locally, use localhost:3000 or a custom API_URL env.
    const apiUrl = process.env.API_URL || 'http://api.railway.internal:3000';

    console.log('[next.config] API rewrite target =', apiUrl);

    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
      // Socket.IO passthrough
      {
        source: '/socket.io/:path*',
        destination: `${apiUrl}/socket.io/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
