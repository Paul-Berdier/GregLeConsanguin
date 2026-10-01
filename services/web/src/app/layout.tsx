import type { Metadata } from 'next';
import { fontVariables } from '@/theme/fonts';
import { QUIPS_SCRIPT } from '@/lib/prefs';
import './globals.css';

export const metadata: Metadata = {
  title: 'Greg le Consanguin — Web Player',
  description: 'Lecteur musical Discord — stream, queue, vidéo.',
  icons: { icon: '/images/icon.png' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning : data-quips, posé par le script du <head>, n'est pas dans le rendu serveur
    <html lang="fr" className={fontVariables} suppressHydrationWarning>
      <head>
        {/* « Répliques de Greg » coupées : appliqué avant la première peinture, connecté ou non (lib/prefs) */}
        <script dangerouslySetInnerHTML={{ __html: QUIPS_SCRIPT }}/>
      </head>
      <body className="antialiased font-body">
        <div className="nightfall" aria-hidden="true"/>
        {children}
      </body>
    </html>
  );
}
