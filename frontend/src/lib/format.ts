/**
 * Mask a CNIC number, keeping only the leading district digits and the
 * final check digit. E.g. "42101-1234567-8" → "42101-*******-8".
 */
export function maskCnic(cnic: string | null | undefined): string {
  if (!cnic) return "";
  // Format: XXXXX-XXXXXXX-X
  const parts = cnic.split("-");
  if (parts.length === 3) {
    return `${parts[0]}-${"*".repeat(parts[1]?.length ?? 7)}-${parts[2]}`;
  }
  // Fallback: mask middle portion.
  if (cnic.length > 4) {
    return cnic.slice(0, 2) + "*".repeat(cnic.length - 3) + cnic.slice(-1);
  }
  return cnic;
}
