import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Offkai Bot',
    short_name: 'Offkai',
    description: 'Offkai RSVP & door check-in',
    start_url: '/',
    display: 'standalone',
    background_color: '#FFF1C2',
    theme_color: '#E51F1F',
    icons: [
      {
        src: '/icon.svg',
        sizes: 'any',
        type: 'image/svg+xml',
      },
    ],
  }
}
