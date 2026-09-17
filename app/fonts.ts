import localFont from "next/font/local"

export const z0Sans = localFont({
  src: "../public/brand/fonts/z0-sans-regular.woff2",
  display: "swap",
  variable: "--font-z0-sans",
})

export const z0Serif = localFont({
  src: "../public/brand/fonts/z0-serif-regular.woff2",
  display: "swap",
  preload: false,
  variable: "--font-z0-serif",
})

export const z0Mono = localFont({
  src: "../public/brand/fonts/z0-mono-regular.woff2",
  display: "swap",
  preload: false,
  variable: "--font-z0-mono",
})
