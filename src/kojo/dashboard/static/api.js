async function request(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return response;
}

export const getJson = async (url) => (await request(url)).json();
export const getText = async (url) => (await request(url)).text();
