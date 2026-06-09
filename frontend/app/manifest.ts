import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'chibachan',
    short_name: 'chibachan',
    description: 'Offkai RSVP frontend',
    start_url: '/',
    display: 'standalone',
    background_color: '#E1D9BC',
    theme_color: '#30364F',
    icons: [
      {
        src: '/icon.svg',
        sizes: 'any',
        type: 'image/svg+xml',
      },
    ],
  }
}
