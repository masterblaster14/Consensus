/**
 * One icon set for both halves of the app. Every glyph is a 24x24 stroke
 * icon that inherits `currentColor`, so it works on any surface in either
 * theme without a variant.
 */

export interface IconProps {
  size?: number
  className?: string
}

function line(size: number, children: React.ReactNode, className?: string) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const Icon = {
  /* Brand ---------------------------------------------------------- */

  Logo: ({ size = 28, className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#FF4D0A" />
      <circle cx="12.5" cy="12.5" r="5" fill="none" stroke="#fff" strokeWidth="2.2" />
      <circle cx="19.5" cy="19.5" r="5" fill="none" stroke="#fff" strokeWidth="2.2" opacity="0.5" />
    </svg>
  ),

  GitHub: ({ size = 18, className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M12 .5A11.5 11.5 0 0 0 .5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.55v-2.1c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.2 1.77 1.2 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.12 3.05.74.81 1.18 1.84 1.18 3.1 0 4.43-2.69 5.4-5.26 5.69.41.36.78 1.06.78 2.14v3.17c0 .3.21.66.8.55A11.5 11.5 0 0 0 23.5 12 11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  ),

  /* Chrome --------------------------------------------------------- */

  Menu: ({ size = 20, className }: IconProps) =>
    line(size, <><path d="M3 6h18" /><path d="M3 12h18" /><path d="M3 18h18" /></>, className),
  Close: ({ size = 20, className }: IconProps) =>
    line(size, <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>, className),
  Search: ({ size = 16, className }: IconProps) =>
    line(size, <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>, className),
  Bell: ({ size = 18, className }: IconProps) =>
    line(size, <><path d="M18 8a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7" /><path d="M10.3 21a2 2 0 0 0 3.4 0" /></>, className),
  Sun: ({ size = 18, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>, className),
  Moon: ({ size = 18, className }: IconProps) =>
    line(size, <path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z" />, className),
  Spinner: ({ size = 18, className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.2" opacity="0.25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  ),

  /* Arrows --------------------------------------------------------- */

  ArrowRight: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></>, className),
  ArrowLeft: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></>, className),
  Chevron: ({ size = 15, className }: IconProps) => line(size, <path d="m9 18 6-6-6-6" />, className),
  ChevronDown: ({ size = 15, className }: IconProps) => line(size, <path d="m6 9 6 6 6-6" />, className),
  External: ({ size = 15, className }: IconProps) =>
    line(size, <><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6" /><path d="M10 14 21 3" /></>, className),

  /* Status --------------------------------------------------------- */

  Check: ({ size = 16, className }: IconProps) => line(size, <path d="M20 6 9 17l-5-5" />, className),
  CheckCircle: ({ size = 18, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="9" /><path d="m8.5 12 2.5 2.5 4.5-5" /></>, className),
  Alert: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4" /><path d="M12 17v.4" /></>, className),
  Info: ({ size = 17, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="9" /><path d="M12 16v-5" /><path d="M12 8v.5" /></>, className),
  Clock: ({ size = 15, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>, className),

  /* Domain --------------------------------------------------------- */

  Grid: ({ size = 17, className }: IconProps) =>
    line(size, <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>, className),
  Bot: ({ size = 17, className }: IconProps) =>
    line(size, <><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 8V4" /><circle cx="12" cy="3" r="1" /><path d="M9 13v1M15 13v1" /><path d="M9.5 17h5" /></>, className),
  Flag: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M5 21V4" /><path d="M5 5h11l-2 3.5L16 12H5" /></>, className),
  Bolt: ({ size = 17, className }: IconProps) => line(size, <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />, className),
  Brain: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M12 5a3 3 0 0 0-6 0 3 3 0 0 0-2 5.2A3 3 0 0 0 6 16a3 3 0 0 0 6 1Z" /><path d="M12 5a3 3 0 0 1 6 0 3 3 0 0 1 2 5.2A3 3 0 0 1 18 16a3 3 0 0 1-6 1Z" /></>, className),
  Pulse: ({ size = 17, className }: IconProps) => line(size, <path d="M3 12h4l3-8 4 16 3-8h4" />, className),
  Scale: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M12 3v18" /><path d="M7 21h10" /><path d="M5 7h14" /><path d="m5 7-3 6h6L5 7Z" /><path d="m19 7-3 6h6l-3-6Z" /></>, className),
  Layers: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="m12 2 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" /></>, className),
  Users: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>, className),
  UserPlus: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M19 8v6M22 11h-6" /></>, className),
  UserMinus: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 11h-6" /></>, className),
  Building: ({ size = 20, className }: IconProps) =>
    line(size, <><path d="M3 21h18" /><path d="M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16" /><path d="M15 9h2a2 2 0 0 1 2 2v10" /><path d="M9 7h2M9 11h2M9 15h2" /></>, className),
  Git: ({ size = 16, className }: IconProps) =>
    line(size, <><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M6 9v6" /><path d="M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" /><path d="M18 9v1a4 4 0 0 1-4 4H9" /></>, className),
  Plug: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M9 2v6M15 2v6" /><path d="M6 8h12v3a6 6 0 0 1-12 0V8Z" /><path d="M12 17v5" /></>, className),
  Radio: ({ size = 20, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="2" /><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 16.2a6 6 0 0 0 0-8.4" /><path d="M4.9 4.9a10 10 0 0 0 0 14.2M19.1 19.1a10 10 0 0 0 0-14.2" /></>, className),
  Calendar: ({ size = 17, className }: IconProps) =>
    line(size, <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 10h18" /><path d="m9 15 2 2 4-4" /></>, className),
  Doc: ({ size = 17, className }: IconProps) =>
    line(size, <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h4" /></>, className),
  Inbox: ({ size = 32, className }: IconProps) =>
    line(size, <><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6l3.5-7Z" /></>, className),

  /* Actions -------------------------------------------------------- */

  Plus: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M12 5v14" /><path d="M5 12h14" /></>, className),
  Trash: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M3 6h18" /><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></>, className),
  Copy: ({ size = 15, className }: IconProps) =>
    line(size, <><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>, className),
  Lock: ({ size = 16, className }: IconProps) =>
    line(size, <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>, className),
  Unlock: ({ size = 16, className }: IconProps) =>
    line(size, <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 7.5-2" /></>, className),
  Globe: ({ size = 16, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z" /></>, className),
  Swap: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M7 4 3 8l4 4" /><path d="M3 8h13a4 4 0 0 1 0 8h-1" /><path d="m17 20 4-4-4-4" opacity="0" /></>, className),
  Settings: ({ size = 17, className }: IconProps) =>
    line(size, <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.1a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-2.9-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 2.9 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.4 1Z" /></>, className),
  LogOut: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></>, className),
  Home: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="m3 10 9-7 9 7v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /><path d="M9 21v-7h6v7" /></>, className),
  Mail: ({ size = 17, className }: IconProps) =>
    line(size, <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>, className),
  Key: ({ size = 17, className }: IconProps) =>
    line(size, <><circle cx="8" cy="14" r="4" /><path d="m11 11 8-8" /><path d="m17 5 2 2" /><path d="m14 8 2 2" /></>, className),
  Shield: ({ size = 20, className }: IconProps) =>
    line(size, <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>, className),
  Eye: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>, className),
  EyeOff: ({ size = 16, className }: IconProps) =>
    line(size, <><path d="M10.6 6.2A9.7 9.7 0 0 1 12 6c6.4 0 10 7 10 7a17 17 0 0 1-3 3.7" /><path d="M6.3 7.4A17 17 0 0 0 2 13s3.6 7 10 7a9.6 9.6 0 0 0 4.3-1" /><path d="m3 3 18 18" /><path d="M9.9 10a3 3 0 0 0 4.2 4.2" /></>, className),
}
