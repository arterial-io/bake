from unittest import TestCase

from bake.environment import *

class TestEnvironment(TestCase):
    def test_construction(self):
        env = Environment()
        self.assertEqual(env.environment, {})

        env = Environment({'a': 1})
        self.assertEqual(env.environment, {'a': 1})

        env = Environment(a=1)
        self.assertEqual(env.environment, {'a': 1})

        env = Environment({'a': 1}, b=2)
        self.assertEqual(env.environment, {'a': 1, 'b': 2})

        env = Environment({'a': 1}, a=2)
        self.assertEqual(env.environment, {'a': 2})

    def test_find(self):
        env = Environment({'a': 1, 'b': {'c': 2, 'd': {'e': 3}}})

        #for invalid in ('z', 'a.z', 'a.b.z', 'a.b.d.z', 'z.a'):
        #    self.assertIsNone(env.find(invalid))
        #    self.assertTrue(env.find(invalid, True))

    def test_get(self):
        env = Environment({'a': 1, 'b': {'c': 2, 'd': {'e': 3}}})

        for invalid in ('z', 'a.z', 'a.b.z', 'a.b.d.z', 'z.a'):
            self.assertIsNone(env.get(invalid))
            self.assertTrue(env.get(invalid, True))

        self.assertEqual(env.get('a'), 1)
        self.assertEqual(env.get('b'), {'c': 2, 'd': {'e': 3}})
        self.assertEqual(env.get('b.c'), 2)
        self.assertEqual(env.get('b.d.e'), 3)

    def test_has(self):
        env = Environment({'a': 1, 'b': {'c': 2, 'd': {'e': 3}}})

        for invalid in ('z', 'a.z', 'a.b.z', 'a.b.d.z', 'z.a'):
            self.assertFalse(env.has(invalid))

        for valid in ('a', 'b', 'b.c', 'b.d.e'):
            self.assertTrue(env.has(valid))

    def test_merge(self):
        env = Environment({'a': 1, 'b': {'c': 2, 'd': {'e': 3}}})
        merged = env.merge({'a': 2, 'b': {'f': 4}})

        self.assertIs(merged, env)
        self.assertEqual(env.environment, {'a': 2, 'b': {'c': 2, 'd': {'e': 3}, 'f': 4}})
