import { Pager as SharedPager } from "@radd/plugin-sdk";
import type { ComponentProps } from "react";
export function Pager(props: ComponentProps<typeof SharedPager>) { return <SharedPager noun="issues" {...props} />; }
