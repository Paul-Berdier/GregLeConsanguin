import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Greg le Consanguin — Web Player',
  description: 'Le gueux musical au service de votre vocal Discord.',
  icons: { icon: '/images/favicon.ico' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className="antialiased overflow-hidden h-screen flex flex-col">
        {children}
      </body>
    </html>
  );
}
