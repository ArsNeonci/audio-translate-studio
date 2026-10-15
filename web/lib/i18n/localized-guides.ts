type Guide = { cause: string; config: string; checks_and_fixes: string[]; commands: string[] };
/** The guides come from the worker already in Vietnamese (core/error_ids.py: what happened, what to do, no paths or commands).
 *  The English wording is written later, from the approved Vietnamese, so for now every language shows them as they are. */
export function localizeGuide(guide: Guide): Guide {
  return guide;
}
