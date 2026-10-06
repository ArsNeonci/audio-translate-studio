// Mirrors worker/config/address-profiles.json and moderation/address.py; labels are uiText keys.
export const addressProfiles = [
  {id: "neutral", label: "Trung tính", description: "addressNeutral"},
  {id: "drama", label: "Drama", description: "addressDrama"},
  {id: "survival", label: "Sinh tồn", description: "addressSurvival"},
  {id: "rebirth", label: "Trọng sinh", description: "addressRebirth"},
] as const;
export type AddressProfile = typeof addressProfiles[number]["id"];
export const isAddressProfile = (value: unknown): value is AddressProfile => addressProfiles.some(item => item.id === value);
// Each voice style suggests the profile of the same genre.
export const addressForStyle = (style: string): AddressProfile => isAddressProfile(style) ? style : "neutral";

export const characterRoles = ["narrator", "family", "lover", "friend", "antagonist", "other"] as const;
export const characterRanks = ["elder", "senior", "peer", "junior"] as const;
export type Character = {id: string; source: string; aliases: string[]; target: string; gender: "male" | "female" | null;
  role: typeof characterRoles[number]; rank: typeof characterRanks[number]; third: string; you: string; auto: boolean; sure?: boolean};
export type CharacterSheet = {version: 1; characters: Character[]};

const text = (value: unknown, limit: number) => typeof value === "string" && value.length <= limit && !/[\x00-\x1f<>]/.test(value);
/** Same limits as validate_sheet() in the worker; returns a normalized sheet or null. */
export function validCharacterSheet(value: unknown): CharacterSheet | null {
  if (!value || typeof value !== "object") return null;
  const sheet = value as {version?: unknown; characters?: unknown};
  if (sheet.version !== 1 || !Array.isArray(sheet.characters) || sheet.characters.length > 200) return null;
  const characters: Character[] = [];
  for (const raw of sheet.characters) {
    const item = raw as Partial<Character>;
    const aliases = Array.isArray(item.aliases) ? item.aliases.map(a => typeof a === "string" ? a.trim() : a).filter(Boolean) : [];
    if (!text(item.source, 20) || !item.source?.trim() || !aliases.length || aliases.length > 10 || !aliases.every(a => text(a, 20))) return null;
    if (!text(item.id ?? "", 20) || !text(item.target ?? "", 40) || !text(item.third ?? "", 20) || !text(item.you ?? "", 20)) return null;
    if (!(item.gender === "male" || item.gender === "female" || item.gender === null)) return null;
    if (!characterRoles.includes(item.role as Character["role"]) || !characterRanks.includes(item.rank as Character["rank"])) return null;
    characters.push({id: (item.id || item.source).trim(), source: item.source.trim(), aliases: aliases as string[], target: (item.target ?? "").trim(),
      gender: item.gender, role: item.role as Character["role"], rank: item.rank as Character["rank"], third: (item.third ?? "").trim(),
      you: (item.you ?? "").trim(), auto: item.auto === true, sure: item.auto === true && item.sure === true});
  }
  return {version: 1, characters};
}
