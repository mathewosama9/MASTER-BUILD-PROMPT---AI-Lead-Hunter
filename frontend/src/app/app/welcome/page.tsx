import { Suspense } from "react";

import { Welcome } from "@/features/onboarding/welcome";

export default function WelcomePage() {
  return (
    <Suspense>
      <Welcome />
    </Suspense>
  );
}
