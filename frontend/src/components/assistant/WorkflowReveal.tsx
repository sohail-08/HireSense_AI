import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { revealSection } from "../common/useSectionReveal";

export function WorkflowReveal() {
  const location = useLocation();
  useEffect(() => {
    const target = location.state?.workflowSection;
    if (typeof target === "string" && /^[a-z][a-z-]+$/.test(target)) return revealSection(target);
  }, [location.key]);
  return null;
}
