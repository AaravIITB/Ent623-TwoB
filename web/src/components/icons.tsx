// A small hand-drawn icon set (stroke icons, 16px grid).
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 16, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconHome = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 7.2 8 2.5l5.5 4.7V13a.5.5 0 0 1-.5.5H10V10H6v3.5H3a.5.5 0 0 1-.5-.5V7.2Z" />
  </Svg>
);
export const IconClients = (p: P) => (
  <Svg {...p}>
    <rect x="2.5" y="3" width="11" height="10.5" rx="1" />
    <path d="M5 6h6M5 8.5h6M5 11h3.5" />
  </Svg>
);
export const IconUsers = (p: P) => (
  <Svg {...p}>
    <circle cx="6" cy="5.5" r="2.3" />
    <path d="M1.8 13.2c.5-2.3 2.2-3.5 4.2-3.5s3.7 1.2 4.2 3.5" />
    <path d="M10.6 3.4a2.2 2.2 0 0 1 0 4.2M12 9.9c1.1.5 1.9 1.6 2.2 3.3" />
  </Svg>
);
export const IconSearch = (p: P) => (
  <Svg {...p}>
    <circle cx="7" cy="7" r="4.3" />
    <path d="m10.3 10.3 3.2 3.2" />
  </Svg>
);
export const IconUpload = (p: P) => (
  <Svg {...p}>
    <path d="M8 10.5V2.8M5 5.6l3-3 3 3M2.8 10.5v2.2c0 .4.3.8.8.8h8.8c.4 0 .8-.4.8-.8v-2.2" />
  </Svg>
);
export const IconDownload = (p: P) => (
  <Svg {...p}>
    <path d="M8 2.8v7.7M5 7.7l3 3 3-3M2.8 10.5v2.2c0 .4.3.8.8.8h8.8c.4 0 .8-.4.8-.8v-2.2" />
  </Svg>
);
export const IconX = (p: P) => (
  <Svg {...p}>
    <path d="m4 4 8 8M12 4l-8 8" />
  </Svg>
);
export const IconCheck = (p: P) => (
  <Svg {...p}>
    <path d="m3.2 8.4 3 3 6.6-6.8" />
  </Svg>
);
export const IconChevronDown = (p: P) => (
  <Svg {...p}>
    <path d="m4 6 4 4 4-4" />
  </Svg>
);
export const IconChevronRight = (p: P) => (
  <Svg {...p}>
    <path d="m6 4 4 4-4 4" />
  </Svg>
);
export const IconChevronLeft = (p: P) => (
  <Svg {...p}>
    <path d="m10 4-4 4 4 4" />
  </Svg>
);
export const IconCopy = (p: P) => (
  <Svg {...p}>
    <rect x="5.5" y="5.5" width="8" height="8" rx="1" />
    <path d="M10.5 5.5V3.3a.8.8 0 0 0-.8-.8H3.3a.8.8 0 0 0-.8.8v6.4c0 .4.4.8.8.8h2.2" />
  </Svg>
);
export const IconMail = (p: P) => (
  <Svg {...p}>
    <rect x="2" y="3.5" width="12" height="9" rx="1" />
    <path d="m2.5 4.2 5.5 4.3 5.5-4.3" />
  </Svg>
);
export const IconChat = (p: P) => (
  <Svg {...p}>
    <path d="M2.6 13.4 3.4 11A5.5 5.5 0 1 1 5.2 12.6l-2.6.8Z" />
  </Svg>
);
export const IconFile = (p: P) => (
  <Svg {...p}>
    <path d="M4 1.8h5l3 3v9.4H4V1.8Z" />
    <path d="M9 1.8v3h3" />
  </Svg>
);
export const IconTrash = (p: P) => (
  <Svg {...p}>
    <path d="M2.8 4.3h10.4M6.3 4.3V2.8h3.4v1.5M4.2 4.3l.6 9h6.4l.6-9" />
  </Svg>
);
export const IconLock = (p: P) => (
  <Svg {...p}>
    <rect x="3" y="7" width="10" height="7" rx="1" />
    <path d="M5.3 7V5a2.7 2.7 0 0 1 5.4 0v2" />
  </Svg>
);
export const IconPlus = (p: P) => (
  <Svg {...p}>
    <path d="M8 3v10M3 8h10" />
  </Svg>
);
export const IconKeyboard = (p: P) => (
  <Svg {...p}>
    <rect x="1.5" y="4" width="13" height="8" rx="1" />
    <path d="M4 6.5h.01M6.5 6.5h.01M9 6.5h.01M11.5 6.5h.01M5 9.5h6" />
  </Svg>
);
export const IconAlert = (p: P) => (
  <Svg {...p}>
    <path d="M8 2 14.5 13.5h-13L8 2Z" />
    <path d="M8 6.5v3M8 11.6h.01" />
  </Svg>
);
export const IconSignOut = (p: P) => (
  <Svg {...p}>
    <path d="M6.5 2.5h-3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3M10.5 11l3-3-3-3M13.5 8H6" />
  </Svg>
);
export const IconUser = (p: P) => (
  <Svg {...p}>
    <circle cx="8" cy="5.5" r="2.6" />
    <path d="M3 13.5c.6-2.6 2.6-4 5-4s4.4 1.4 5 4" />
  </Svg>
);
