import { useEffect } from "react";
import { usePagedDirectory } from "@radd/plugin-sdk";
import { PAGE_SPACES_PAGE_SIZE, pageSpacesPageQuery } from "./queries";

/** The spaces directory: a searched, bounded window that steps back a page when its last row goes. */
export function usePageSpaceDirectory(enabled = true) {
  const directory = usePagedDirectory("page-spaces", (q, page) => ({ ...pageSpacesPageQuery(q, page), enabled }),
    { pageSize: PAGE_SPACES_PAGE_SIZE });
  const { page, total, isSuccess, setPage } = directory;
  useEffect(() => {
    if (isSuccess && page > 0 && page * PAGE_SPACES_PAGE_SIZE >= total)
      setPage(Math.max(0, Math.ceil(total / PAGE_SPACES_PAGE_SIZE) - 1));
  }, [page, total, isSuccess]);
  return directory;
}
