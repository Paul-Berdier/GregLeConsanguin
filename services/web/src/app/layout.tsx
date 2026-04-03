import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Greg le Consanguin — Web Player',
  description: 'Lecteur musical Discord — stream, queue, Spotify, vidéo.',
  icons: { icon: '/images/icon.png' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className="antialiased font-body">{children}</body>
    </html>
  );
}
