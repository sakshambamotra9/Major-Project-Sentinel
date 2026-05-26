import { createClient } from '@supabase/supabase-js';

// Supabase Credentials
const supabaseUrl = 'https://ssnedxdyhnczhvkdrkyg.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNzbmVkeGR5aG5jemh2a2Rya3lnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjA0NzAsImV4cCI6MjA5NTI5NjQ3MH0.vVXumzUQZrtGnjwf_NJl2Dtmf73U01uNb_Fxmq_uJSE';

export const supabase = createClient(supabaseUrl, supabaseKey);
