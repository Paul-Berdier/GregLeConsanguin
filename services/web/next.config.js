/** @type {import('next').NextConfig} */
const nextConfig = {
  // output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'i.ytimg.com' },
      { protocol: 'https', hostname: 'img.youtube.com' },
      { protocol: 'https', hostname: 'cdn.discordapp.com' },
    ],
  },

  async rewrites() {
    const apiUrl = process.env.API_URL || 'http://api.railway.internal:3000';

    console.log('[next.config] API rewrite target =', apiUrl);

    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;