// Browser infrastructure is disabled in the offline planning prototype.
export async function POST() {
  return Response.json(
    { error: 'Browser sessions and X interactions are disabled. Use python3 -m server.' },
    { status: 410 }
  )
}
