/** ISO 3166-1 alpha-2 codes (same list as backend/app/core/countries.py); names come from Intl.DisplayNames. */
const CODES =
  "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ " +
  "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO " +
  "FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE " +
  "JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO " +
  "MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW " +
  "PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM " +
  "TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW";

export const COUNTRY_CODES = CODES.split(" ");

/** Shown first in the picker: where most customers come from. */
export const COMMON_COUNTRIES = ["EG", "SA", "AE", "KW", "QA", "BH", "OM", "JO", "LB", "IQ", "MA", "DZ", "TN", "LY", "SD", "PS", "SY", "YE"];

export function countryName(code: string | null | undefined, locale: string): string {
  if (!code) return "—";
  try {
    return new Intl.DisplayNames([locale === "ar" ? "ar" : "en"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

export function countryFlag(code: string | null | undefined): string {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return "";
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

/** {code, name} sorted by name in the UI language, common countries first. */
export function countryOptions(locale: string): { code: string; name: string; common: boolean }[] {
  const collator = new Intl.Collator(locale === "ar" ? "ar" : "en");
  const all = COUNTRY_CODES.map((code) => ({ code, name: countryName(code, locale), common: COMMON_COUNTRIES.includes(code) }));
  const common = COMMON_COUNTRIES.map((c) => all.find((x) => x.code === c)!).filter(Boolean);
  const rest = all.filter((x) => !x.common).sort((a, b) => collator.compare(a.name, b.name));
  return [...common, ...rest];
}
