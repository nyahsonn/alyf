import Image from "next/image";

const LOCKUP_ASPECT = 354 / 483;
const SYMBOL_ASPECT = 316 / 286;

/**
 * The ALYF wordmark: icon stacked over the "ALYF" wordmark. Two
 * theme-matched PNGs (light-surface ink vs. dark-surface ink, same layout,
 * swapped via prefers-color-scheme) rather than one asset -- the source
 * lockup's ink is nearly invisible against the wrong surface color
 * otherwise.
 */
export function Logo({ height = 96, className }: { height?: number; className?: string }) {
  const width = Math.round(height * LOCKUP_ASPECT);
  return (
    <span className={className} style={{ display: "inline-block", height, width }}>
      <Image
        src="/logo-lockup-light.png"
        alt="ALYF"
        width={width}
        height={height}
        priority
        className="block dark:hidden"
      />
      <Image
        src="/logo-lockup-dark.png"
        alt="ALYF"
        width={width}
        height={height}
        priority
        className="hidden dark:block"
      />
    </span>
  );
}

/** The icon alone, no wordmark -- for tight spaces. */
export function LogoSymbol({ height = 48, className }: { height?: number; className?: string }) {
  const width = Math.round(height * SYMBOL_ASPECT);
  return (
    <span className={className} style={{ display: "inline-block", height, width }}>
      <Image
        src="/logo-symbol-light.png"
        alt="ALYF"
        width={width}
        height={height}
        priority
        className="block dark:hidden"
      />
      <Image
        src="/logo-symbol-dark.png"
        alt="ALYF"
        width={width}
        height={height}
        priority
        className="hidden dark:block"
      />
    </span>
  );
}
