/** Presentation roles for single-user Kraken. Not a production auth boundary. */
export type KrakenPresentationRole = "USER" | "OWNER";

export const ROLE_STORAGE_KEY = "kraken.presentationRole";
