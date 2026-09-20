"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import ConfirmDialog, { type ConfirmationOptions } from "./ConfirmDialog";

type Ask = (options: ConfirmationOptions) => Promise<boolean>;
const Context = createContext<Ask | null>(null);

export function useConfirmation() {
  const ask = useContext(Context);
  if (!ask) throw new Error("ConfirmationProvider is required");
  return ask;
}

export default function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmationOptions | null>(null);
  const resolve = useRef<((confirmed: boolean) => void) | null>(null);
  const ask = useCallback<Ask>((next) => {
    // Repeated clicks never create multiple pending actions.
    if (resolve.current) return Promise.resolve(false);
    return new Promise<boolean>((done) => { resolve.current = done; setOptions(next); });
  }, []);
  function finish(confirmed: boolean) {
    resolve.current?.(confirmed);
    resolve.current = null;
    setOptions(null);
  }
  useEffect(() => () => { resolve.current?.(false); }, []);
  return <Context.Provider value={ask}>
    {children}
    {options && <ConfirmDialog {...options} open onCancel={() => finish(false)} onConfirm={() => finish(true)} />}
  </Context.Provider>;
}
