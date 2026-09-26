import { createElement, type ComponentType, type ReactNode } from "react";
import { useProvided, type HostComponents } from "./host-registry";

type PropsOf<K extends keyof HostComponents> = NonNullable<HostComponents[K]> extends ComponentType<infer P> ? P : never;

/** A wrapper that renders the component the host provided as `name`, else `fallback` — something
 *  plain, never a broken page. The fallback renders as its own component, so it may use hooks. */
export function bridged<K extends keyof HostComponents>(name: K, fallback: (props: PropsOf<K>) => ReactNode) {
  function Bridge(props: PropsOf<K>): ReactNode {
    const Host = useProvided()[name] as ComponentType<PropsOf<K>> | undefined;
    return createElement((Host ?? fallback) as ComponentType<object>, props as object);
  }
  Bridge.displayName = name;
  return Bridge;
}
