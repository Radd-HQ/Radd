import { useEffect } from "react";
import { usePagedDirectory } from "@radd/plugin-sdk";
import { PAGE_SPACES_PAGE_SIZE, pageSpacesPageQuery } from "./queries";

/** Step back a page when the current one's last row goes. */
export function useStepBackWhenEmptied({ page, pageSize, total, isSuccess, setPage }: {
  page: number; pageSize: number; total: number; isSuccess: boolean; setPage: (page: number) => void;
}) {
  useEffect(() => {
    if (isSuccess && page > 0 && page * pageSize >= total) setPage(Math.max(0, Math.ceil(total / pageSize) - 1));
  }, [page, total, isSuccess]);
}

/** The spaces directory: a searched, bounded window. */
export function usePageSpaceDirectory(enabled = true) {
  const directory = usePagedDirectory("page-spaces", (q, page) => ({ ...pageSpacesPageQuery(q, page), enabled }),
    { pageSize: PAGE_SPACES_PAGE_SIZE });
  useStepBackWhenEmptied(directory);
  return directory;
}
