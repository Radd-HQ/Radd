import { useEffect } from "react";
import { useDirectory } from "./useDirectory";
import { PAGE_SPACES_PAGE_SIZE, pageSpacesPageQuery } from "./queries/pages";

export function usePageSpaceDirectory(enabled = true) {
  const directory = useDirectory("page-spaces", PAGE_SPACES_PAGE_SIZE, (q, page) => ({
    ...pageSpacesPageQuery(q, page), enabled,
  }));
  const { page, total, isSuccess } = directory;
  useEffect(() => {
    if (isSuccess && page > 0 && page * PAGE_SPACES_PAGE_SIZE >= total)
      directory.setPage(Math.max(0, Math.ceil(total / PAGE_SPACES_PAGE_SIZE) - 1));
  }, [page, total, isSuccess]);
  return directory;
}
