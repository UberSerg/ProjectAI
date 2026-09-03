import { useHelpOptional } from "./HelpContext";

/** Page-level [Справка] action that opens the shared help drawer. */
export function PageHelp({ pageId }: { pageId: string }) {
  const help = useHelpOptional();
  if (!help) return null;
  return (
    <button type="button" className="secondary" onClick={() => help.openPage(pageId)}>
      Справка
    </button>
  );
}
