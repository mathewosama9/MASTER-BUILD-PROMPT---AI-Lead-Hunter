import { ContactPage } from "@/features/site/contact";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/contact", ar.contact.metaTitle, ar.contact.metaDescription);

export default function Page() {
  return <ContactPage />;
}
