import type { Metadata } from 'next';
import { fontVariables } from '@/theme/fonts';
import './globals.css';

export const metadata: Metadata = {
  title: 'Greg le Consanguin — Web Player',
  description: 'Lecteur musical Discord — stream, queue, vidéo.',
  icons: { icon: '/images/icon.png' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={fontVariables}>
      <body className="antialiased font-body">
        <div className="nightfall" aria-hidden="true"/>
        {children}
      </body>
    </html>
  );
}
