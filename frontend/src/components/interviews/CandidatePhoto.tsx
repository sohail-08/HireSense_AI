import { useEffect, useState } from "react";
import { apiBlob } from "../../api/apiClient";
import { MeetingIcon } from "./MeetingIcon";

export function CandidatePhoto({ interviewId, name }: { interviewId: number; name: string }) {
  const [photo, setPhoto] = useState<{ interviewId: number; url: string }>();
  useEffect(() => {
    let active = true;
    let url: string | undefined;
    const controller = new AbortController();
    setPhoto(undefined);
    async function load() {
      try {
        const blob = await apiBlob(`/interview-rooms/${interviewId}/candidate-photo`, { signal: controller.signal });
        if (!active || !blob.size || blob.type !== "image/jpeg") return;
        url = URL.createObjectURL(blob);
        setPhoto({ interviewId, url });
      } catch {
        // Missing/inaccessible uploads must not block candidate information.
      }
    }
    void load();
    return () => { active = false; controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [interviewId]);
  const current = photo?.interviewId === interviewId ? photo.url : undefined;
  return <span className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-indigo-100 bg-indigo-50 text-indigo-700">
    {current ? <img src={current} alt={`${name}'s uploaded application photo`} className="h-full w-full object-cover"
      referrerPolicy="no-referrer" onError={() => setPhoto(undefined)} />
      : <MeetingIcon name="person" className="h-8 w-8" />}
  </span>;
}
