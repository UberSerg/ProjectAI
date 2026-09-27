/** Build-time metadata for OWNER view. Never invent values at runtime. */

export interface BuildMeta {
  version: string;
  gitTag: string;
  gitSha: string | null;
  buildTime: string | null;
}

export function getBuildMeta(version: string): BuildMeta {
  const sha = (import.meta.env.VITE_GIT_SHA as string | undefined)?.trim() || null;
  const buildTime = (import.meta.env.VITE_BUILD_TIME as string | undefined)?.trim() || null;
  return {
    version,
    gitTag: `v${version}`,
    gitSha: sha && sha.length > 0 ? sha : null,
    buildTime: buildTime && buildTime.length > 0 ? buildTime : null,
  };
}
