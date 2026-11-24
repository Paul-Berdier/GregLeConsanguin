'use client';

import { useId, useLayoutEffect, useRef, useState } from 'react';
import { useLibrary } from '@/hooks/useLibrary';
import { DEFAULT_LIMITS } from '@/lib/library';
import { tx } from '@/theme/copy.extra';

export type NameFormProps = {
  /** Nom proposé (sélectionné à l'ouverture) ; '' : champ vide. */
  initial: string;
  submitLabel: string;
  submitAria: string;
  /** true : accepté, le formulaire se ferme (le parent le démonte) ; false : il reste, le Héraut a dit pourquoi. */
  onSubmit: (name: string) => boolean;
  onCancel: () => void;
};

/**
 * Nom d'une playlist saisi en ligne (nouvelle, file enregistrée, renommée, menu du titre en lecture) : le champ prend le
 * focus à l'ouverture, Entrée valide, Échap annule sans fermer le popover qui le contient. Styles : library.css.
 */
export default function NameForm({ initial, submitLabel, submitAria, onSubmit, onCancel }: NameFormProps) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);
  const id = useId();
  const max = useLibrary((s) => s.lib?.limits.name ?? DEFAULT_LIMITS.name);

  useLayoutEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);

  return (
    <form className="lform" onSubmit={(e) => { e.preventDefault(); onSubmit(value); }}>
      <label className="sr" htmlFor={id}>{tx('library.nameLabel')}</label>
      <input id={id} ref={ref} className="lfield" value={value} maxLength={max} autoComplete="off" spellCheck={false}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel(); } }}/>
      <button type="submit" className="lbtn primary" aria-label={submitAria}>{submitLabel}</button>
      <button type="button" className="lbtn" aria-label={tx('library.cancel')} onClick={onCancel}>{tx('library.cancel')}</button>
    </form>
  );
}
